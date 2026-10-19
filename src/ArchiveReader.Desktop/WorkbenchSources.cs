using System.Diagnostics;
using System.Text.Json.Nodes;
using System.Windows;
using System.Windows.Controls;

namespace ArchiveReader;

public partial class WorkbenchWindow
{
    string? sourceSignature;
    Dictionary<string,TextBox> SourceBookFields()=>new() { ["archive"]=SourceArchive,["country"]=SourceCountry,["collection"]=SourceCollection,["fonds"]=SourceFonds,["inventory"]=SourceInventory,["file"]=SourceFile,["title"]=SourceTitle,["place"]=SourcePlace,["url"]=SourceUrl,["accessed"]=SourceAccessed,["rights"]=SourceRights,["notes"]=SourceNotes };
    Dictionary<string,TextBox> SourcePageFields()=>new() { ["folio"]=SourceFolio,["original_page"]=SourceOriginalPage,["image_number"]=SourceImageNumber,["scan_label"]=SourceScanLabel,["entry_number"]=SourceEntryNumber,["page_url"]=SourcePageUrl,["page_notes"]=SourcePageNotes };
    async Task LoadSourceCard()
    {
        var card=await Call("source_card",new() { ["id"]=page.Id });
        foreach(var field in SourceBookFields()) field.Value.Text=card["book"]![field.Key]?.ToString() ?? "";
        foreach(var field in SourcePageFields()) field.Value.Text=card["page_values"]![field.Key]?.ToString() ?? "";
        sourceSignature=card["signature"]!.ToString(); SourceCitation.Text=card["citation"]!.ToString();
        SourceInheritance.Text=card["inherited"]!.GetValue<bool>()?T("Джерело успадковано від оригіналу. Збереження створить окрему картку цієї копії."):"";
    }
    async void SaveSourceCard(object sender,RoutedEventArgs e)=>await Run(async()=>
    {
        var book=new JsonObject(); foreach(var field in SourceBookFields()) book[field.Key]=field.Value.Text;
        var values=new JsonObject(); foreach(var field in SourcePageFields()) values[field.Key]=field.Value.Text;
        await Call("source_card",new() { ["id"]=page.Id,["book"]=book,["page_values"]=values,["expected"]=sourceSignature });
        await LoadSourceCard(); Status.Text=T("Картку джерела збережено. Дані додаються до експорту.");
    });
    void OpenSourceLink(object sender,RoutedEventArgs e)
    {
        string value=SourcePageUrl.Text.Trim().Length>0?SourcePageUrl.Text.Trim():SourceUrl.Text.Trim();
        if(!Uri.TryCreate(value,UriKind.Absolute,out var uri) || uri.Scheme is not ("http" or "https")) { Status.Text=T("Вкажіть повне посилання HTTP або HTTPS."); return; }
        Process.Start(new ProcessStartInfo(uri.AbsoluteUri) { UseShellExecute=true });
    }
    void CopySourceCitation(object sender,RoutedEventArgs e)
    { if(SourceCitation.Text.Length>0) { Clipboard.SetText(SourceCitation.Text); Status.Text=T("Посилання для цитування скопійовано."); } }
}
